from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_dg10_tier2_blind_package as tier2
from scripts import run_dg10_benchmark_dev_smoke as dev_smoke

DATE = "2026-08-22"
CANDIDATE = "candidate.5"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
DATA_BOUNDARY_ACK = "tier3-same-vllm-public-dev-characterization-only"
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-tier3-same-vllm-judge-{CANDIDATE}-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = ROOT.parent / "evidence/dg10-tier3-same-vllm-judge"
IDENTITY_REPORT = ROOT / "docs/reports/DG-10-vllm-local-identity-2026-08-20.json"
QUALITY_CONTRACT = tier2.QUALITY_CONTRACT
QUALITY_CONTRACT_SHA256 = tier2.QUALITY_CONTRACT_SHA256
QUALITY_REPORT = tier2.QUALITY_REPORT
QUALITY_REPORT_SHA256 = tier2.QUALITY_REPORT_SHA256
THREE_ARM_REPORT = tier2.THREE_ARM_REPORT
THREE_ARM_REPORT_SHA256 = tier2.THREE_ARM_REPORT_SHA256
THREE_ARM_SIDECAR = tier2.THREE_ARM_SIDECAR
THREE_ARM_SIDECAR_SHA256 = tier2.THREE_ARM_SIDECAR_SHA256
ARMS = tier2.ARMS
CASE_IDS = tier2.TIER2_CASES
MAX_OUTPUT_TOKENS = 256
CORRECTNESS = ("CORRECT", "PARTIALLY_CORRECT", "INCORRECT", "AMBIGUOUS_REFERENCE")
SUPPORT = ("SUPPORTED", "UNSUPPORTED", "CONFLICTING", "NOT_ASSESSABLE")
UNCERTAINTY = ("APPROPRIATE", "OVERCONFIDENT", "UNNECESSARILY_ABSTAINED")
REASON_CODES = (
    "LATEST_STATE",
    "TEMPORAL_ORDER",
    "ENTITY_MISMATCH",
    "MISSING_DETAIL",
    "EXTRA_UNSUPPORTED_DETAIL",
    "REFERENCE_AMBIGUITY",
    "OTHER_REDACTED_NOTE",
)


class Tier3JudgeError(RuntimeError):
    pass


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return dev_smoke._sha256_file(path)


def _json_sha256(value: object) -> str:
    return dev_smoke._json_sha256(value)


def _judge_contract() -> dict[str, Any]:
    return {
        "version": "DG10_TIER3_SAME_VLLM_JUDGE_V1",
        "model_id": MODEL_ID,
        "temperature": 0,
        "seed": 20260821,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "tool_choice": "none",
        "include_reasoning": False,
        "response_format": "LOCAL_VLLM_STRICT_JSON_SCHEMA",
        "release_input": False,
        "system_prompt": (
            "You are a characterization-only answer auditor. Compare one candidate answer "
            "with the question, public reference answer, and the bounded evidence actually "
            "available to that answer. Do not reward unsupported detail. Return exactly one "
            "JSON object and no markdown or extra text."
        ),
        "output_schema": {
            "correctness": list(CORRECTNESS),
            "support_status": list(SUPPORT),
            "uncertainty_calibration": list(UNCERTAINTY),
            "reason_codes": {
                "allowed_values": list(REASON_CODES),
                "cardinality": "zero or more; empty means no specific rubric code",
            },
            "explanation": "non-empty string; 80 words is advisory and never a score",
        },
        "normalization_contract": {
            "reason_codes": "ordered-set semantics; duplicate enum values are removed after raw output capture because the local grammar backend rejects JSON-Schema uniqueItems",
            "explanation": "raw text is retained externally; word count and advisory-overrun flag are recorded, but text is not truncated or scored",
            "all_other_fields": "no normalization",
        },
        "user_template": (
            "Question:\n{question}\n\nPublic reference answer(s):\n{reference}\n\n"
            "Bounded evidence available to the candidate:\n{evidence}\n\n"
            "Candidate answer:\n{answer}\n\n"
            'Return exactly: {{"correctness":"...","support_status":"...",'
            '"uncertainty_calibration":"...","reason_codes":["..."],'
            '"explanation":"..."}}'
        ),
    }


def _structured_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "dg10_tier3_judgment",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "correctness",
                    "support_status",
                    "uncertainty_calibration",
                    "reason_codes",
                    "explanation",
                ],
                "properties": {
                    "correctness": {"type": "string", "enum": list(CORRECTNESS)},
                    "support_status": {"type": "string", "enum": list(SUPPORT)},
                    "uncertainty_calibration": {
                        "type": "string",
                        "enum": list(UNCERTAINTY),
                    },
                    "reason_codes": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(REASON_CODES)},
                    },
                    "explanation": {"type": "string"},
                },
            },
        },
    }


def _complete_structured(
    client: dev_smoke.LocalVllmClient,
    messages: Sequence[Mapping[str, Any]],
    *,
    request_key: str,
    expected_prompt_tokens: int,
) -> dev_smoke.CompletionResult:
    payload = {
        "model": MODEL_ID,
        "messages": list(messages),
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
        "seed": 20260821,
        "tool_choice": "none",
        "chat_template_kwargs": {"enable_thinking": False},
        "include_reasoning": False,
        "response_format": _structured_response_format(),
        "cache_salt": _sha256_bytes(f"dg10-tier3-candidate5:{request_key}".encode()),
    }
    started = time.perf_counter()
    try:
        response, headers = dev_smoke.vllm_local_ab._post_json(
            client.base_url,
            "/v1/chat/completions",
            payload,
            timeout=client.timeout,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        text, usage, native_id, receipt_sha256, finish_reason = (
            dev_smoke._validate_benchmark_completion(
                response,
                headers,
                expected_prompt_tokens=expected_prompt_tokens,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
        )
    except dev_smoke.vllm_local_ab.LocalVllmCaptureError as exc:
        raise Tier3JudgeError("structured local vLLM completion failed") from exc
    return dev_smoke.CompletionResult(
        text=text,
        native_request_id=native_id,
        usage=usage,
        latency_ms=latency_ms,
        native_receipt_sha256=receipt_sha256,
        finish_reason=finish_reason,
    )


def _messages(record: Mapping[str, Any]) -> list[dict[str, str]]:
    contract = _judge_contract()
    gold = record.get("gold_answers")
    if not isinstance(gold, list) or not all(isinstance(item, str) for item in gold):
        raise Tier3JudgeError("judge reference answer contract drift")
    question = record.get("question")
    answer = record.get("parsed_answer")
    evidence = record.get("memory_context")
    if (
        not isinstance(question, str)
        or not isinstance(answer, str)
        or not isinstance(evidence, str)
    ):
        raise Tier3JudgeError("judge raw input contract drift")
    user = contract["user_template"].format(
        question=question,
        reference=json.dumps(gold, ensure_ascii=False),
        evidence=evidence if evidence else "[none supplied]",
        answer=answer,
    )
    return [
        {"role": "system", "content": contract["system_prompt"]},
        {"role": "user", "content": user},
    ]


def _parse_judgment(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise Tier3JudgeError("judge output is not exact JSON") from exc
    if not isinstance(value, dict) or set(value) != {
        "correctness",
        "support_status",
        "uncertainty_calibration",
        "reason_codes",
        "explanation",
    }:
        raise Tier3JudgeError("judge output object keys drift")
    if value["correctness"] not in CORRECTNESS:
        raise Tier3JudgeError("judge correctness label drift")
    if value["support_status"] not in SUPPORT:
        raise Tier3JudgeError("judge support label drift")
    if value["uncertainty_calibration"] not in UNCERTAINTY:
        raise Tier3JudgeError("judge uncertainty label drift")
    reason_codes = value["reason_codes"]
    if not isinstance(reason_codes, list) or any(
        item not in REASON_CODES for item in reason_codes
    ):
        raise Tier3JudgeError("judge reason code contract drift")
    normalized_reason_codes = list(dict.fromkeys(reason_codes))
    explanation = value["explanation"]
    if not isinstance(explanation, str) or not explanation.strip():
        raise Tier3JudgeError("judge explanation contract drift")
    explanation_word_count = len(explanation.split())
    return {
        "correctness": value["correctness"],
        "support_status": value["support_status"],
        "uncertainty_calibration": value["uncertainty_calibration"],
        "reason_codes": normalized_reason_codes,
        "normalization": {
            "duplicate_reason_codes_removed": len(reason_codes)
            - len(normalized_reason_codes),
            "explanation_word_count": explanation_word_count,
            "explanation_exceeds_advisory_80_words": explanation_word_count > 80,
        },
        "explanation": explanation.strip(),
    }


def _ordered_records(sidecar: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    grouped = tier2._records_by_case(sidecar)
    records = [grouped[case_id][arm] for case_id in CASE_IDS for arm in ARMS]
    records.sort(
        key=lambda record: (
            _sha256_bytes(
                f"dg10-tier3-v1\0{record['case_id']}\0{record['arm']}".encode()
            ),
            str(record["case_id"]),
            str(record["arm"]),
        )
    )
    if len(records) != 36:
        raise Tier3JudgeError("Tier-3 record denominator drift")
    return records


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction)))
    return round(ordered[index], 3)


def _aggregates(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    scores = {"CORRECT": 1.0, "PARTIALLY_CORRECT": 0.5, "INCORRECT": 0.0}
    for arm in ARMS:
        selected = [item for item in records if item["arm"] == arm]
        if len(selected) != 12:
            raise Tier3JudgeError("Tier-3 arm denominator drift")
        score_values = [
            scores[str(item["judgment"]["correctness"])]
            for item in selected
            if item["judgment"]["correctness"] in scores
        ]
        result[arm] = {
            "case_count": len(selected),
            "correctness_distribution": dict(
                sorted(
                    Counter(
                        item["judgment"]["correctness"] for item in selected
                    ).items()
                )
            ),
            "support_distribution": dict(
                sorted(
                    Counter(
                        item["judgment"]["support_status"] for item in selected
                    ).items()
                )
            ),
            "uncertainty_distribution": dict(
                sorted(
                    Counter(
                        item["judgment"]["uncertainty_calibration"] for item in selected
                    ).items()
                )
            ),
            "ordinal_correctness_mean_excluding_ambiguous_reference": (
                round(mean(score_values), 6) if score_values else None
            ),
            "ambiguous_reference_count": sum(
                item["judgment"]["correctness"] == "AMBIGUOUS_REFERENCE"
                for item in selected
            ),
        }
    return result


def _write_journal_line(stream: Any, value: Mapping[str, Any]) -> None:
    stream.write(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    stream.flush()
    os.fsync(stream.fileno())


def _journal_summary(path: Path, run_id: str) -> dict[str, Any]:
    if not path.exists():
        return {"status": "NOT_CREATED", "completed_native_model_calls": 0}
    lines = path.read_text(encoding="utf-8").splitlines()
    values = [json.loads(line) for line in lines if line]
    if (
        not values
        or values[0].get("schema") != "milai.dg10.tier3-progress-journal.v1"
        or values[0].get("run_id") != run_id
    ):
        raise Tier3JudgeError("progress journal header drift")
    records = values[1:]
    native_ids = [str(item["native_request_id"]) for item in records]
    if len(native_ids) != len(set(native_ids)):
        raise Tier3JudgeError("progress journal native request ID duplication")
    return {
        "status": "WRITTEN_HASH_BOUND",
        "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        "sha256": _sha256_file(path),
        "size": path.stat().st_size,
        "mode": "0600",
        "completed_native_model_calls": len(records),
        "unique_native_request_ids": len(set(native_ids)),
        "native_request_ids_sha256": _json_sha256(sorted(native_ids)),
        "input_tokens": sum(int(item["usage"]["input_tokens"]) for item in records),
        "output_tokens": sum(int(item["usage"]["output_tokens"]) for item in records),
        "last_ordinal": int(records[-1]["ordinal"]) if records else None,
    }


def run_judge(
    *,
    client: dev_smoke.LocalVllmClient,
    sidecar: Mapping[str, Any],
    run_id: str,
    journal_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = datetime.now(UTC)
    source_records = _ordered_records(sidecar)
    public_records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    native_ids: set[str] = set()
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(journal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as journal:
        _write_journal_line(
            journal,
            {
                "schema": "milai.dg10.tier3-progress-journal.v1",
                "run_id": run_id,
                "candidate": CANDIDATE,
                "created_at": started.isoformat(),
                "repository_retention": "PROHIBITED_RAW_REPO_EXTERNAL_ONLY",
            },
        )
        for ordinal, source in enumerate(source_records):
            messages = _messages(source)
            prompt_tokens = client.count_tokens(messages)
            if prompt_tokens > 32768:
                raise Tier3JudgeError("judge prompt token ceiling exceeded")
            completion = _complete_structured(
                client,
                messages,
                request_key=f"{run_id}:{ordinal}:{source['case_id']}:{source['arm']}",
                expected_prompt_tokens=prompt_tokens,
            )
            journal_record = {
                "ordinal": ordinal,
                "case_id": source["case_id"],
                "category": source["category"],
                "arm": source["arm"],
                "messages": messages,
                "candidate_answer": source["parsed_answer"],
                "reference_answers": source["gold_answers"],
                "bounded_evidence": source["memory_context"],
                "raw_judge_output": completion.text,
                "native_request_id": completion.native_request_id,
                "native_receipt_sha256": completion.native_receipt_sha256,
                "finish_reason": completion.finish_reason,
                "latency_ms": round(completion.latency_ms, 3),
                "usage": {
                    "input_tokens": int(completion.usage["input_tokens"]),
                    "output_tokens": int(completion.usage["output_tokens"]),
                },
                "prompt_sha256": _json_sha256(messages),
                "raw_output_sha256": _sha256_bytes(completion.text.encode()),
            }
            # Persist the native receipt and raw output before strict parsing. A
            # malformed model result therefore remains auditable without retry.
            _write_journal_line(journal, journal_record)
            if completion.native_request_id in native_ids:
                raise Tier3JudgeError("duplicate native request ID")
            native_ids.add(completion.native_request_id)
            judgment = _parse_judgment(completion.text)
            public_judgment = {
                key: value for key, value in judgment.items() if key != "explanation"
            }
            public_judgment["explanation_sha256"] = _sha256_bytes(
                judgment["explanation"].encode()
            )
            record = {
                "ordinal": ordinal,
                "case_id": source["case_id"],
                "category": source["category"],
                "arm": source["arm"],
                "judgment": public_judgment,
                "native_request_id": completion.native_request_id,
                "native_receipt_sha256": completion.native_receipt_sha256,
                "finish_reason": completion.finish_reason,
                "latency_ms": round(completion.latency_ms, 3),
                "usage": journal_record["usage"],
                "prompt_sha256": journal_record["prompt_sha256"],
                "raw_output_sha256": journal_record["raw_output_sha256"],
            }
            public_records.append(record)
            raw_records.append({**journal_record, "parsed_judgment": judgment})
    if len(public_records) != 36 or len(native_ids) != 36:
        raise Tier3JudgeError("Tier-3 terminal denominator drift")
    ended = datetime.now(UTC)
    latencies = [float(item["latency_ms"]) for item in public_records]
    report = {
        "schema": "milai.dg10.tier3-same-vllm-judge.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "run_id": run_id,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "status": "TIER3_SAME_VLLM_DEV_CHARACTERIZATION_COMPLETE",
        "quality_outcome": "LOCAL_VLLM_PROTOCOL_CHARACTERIZATION_ONLY",
        "release_input": False,
        "sole_release_authority": False,
        "may_override_tier1_or_safety": False,
        "test_access_authorized": False,
        "test_labels_or_outputs_opened": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "model_id": MODEL_ID,
        "identity": dict(client.identity_evidence),
        "inputs": {
            "quality_contract_sha256": QUALITY_CONTRACT_SHA256,
            "quality_report_sha256": QUALITY_REPORT_SHA256,
            "three_arm_report_sha256": THREE_ARM_REPORT_SHA256,
            "three_arm_raw_sidecar_sha256": THREE_ARM_SIDECAR_SHA256,
            "case_ids": list(CASE_IDS),
            "case_ids_sha256": _json_sha256(list(CASE_IDS)),
            "case_count": len(CASE_IDS),
            "answer_count": len(public_records),
            "judge_contract": _judge_contract(),
            "judge_contract_sha256": _json_sha256(_judge_contract()),
            "execution_order": "SHA256_DG10_TIER3_V1_CASE_ARM_INTERLEAVE",
            "execution_order_sha256": _json_sha256(
                [(item["case_id"], item["arm"]) for item in source_records]
            ),
        },
        "records": public_records,
        "aggregates": {
            "logical_judgments": len(public_records),
            "native_model_calls": len(native_ids),
            "unique_native_request_ids": len(native_ids),
            "native_request_ids_sha256": _json_sha256(sorted(native_ids)),
            "tokenizer_requests": client.tokenizer_requests,
            "input_tokens": sum(
                item["usage"]["input_tokens"] for item in public_records
            ),
            "output_tokens": sum(
                item["usage"]["output_tokens"] for item in public_records
            ),
            "latency_ms": {
                "mean": round(mean(latencies), 3),
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
                "p99": _percentile(latencies, 0.99),
            },
            "by_arm": _aggregates(public_records),
        },
        "gate_results": {
            "same_frozen_vllm_identity": "PASS",
            "one_judge_call_per_answer": "PASS",
            "hidden_or_retry_calls": "PASS_ZERO",
            "dev_only_test_boundary": "PASS_CLOSED",
            "tier3_characterization": "COMPLETE",
            "release_authority": "DENIED_BY_CONTRACT",
        },
        "release_effect": {
            "tier1_below_target": "UNCHANGED",
            "may_authorize_test": False,
            "may_support_local_candidate_claim": False,
        },
        "known_limits": [
            "The judge is the same model family and endpoint that produced the candidate answers, so self-evaluation bias is expected.",
            "The 12 cases are a pre-frozen public dev audit subset, not test and not an official LongMemEval judge score.",
            "Tier-3 cannot vote over Tier-1 deterministic, safety, or hidden-call failures.",
        ],
        "repo_external_sidecar": {
            "status": "PENDING_BIND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        },
        "repo_external_progress_journal": _journal_summary(journal_path, run_id),
    }
    raw_sidecar = {
        "schema": "milai.dg10.tier3-same-vllm-judge-raw-sidecar.v1",
        "run_id": run_id,
        "created_at": ended.isoformat(),
        "data_classification": "PUBLIC_BENCHMARK_DEV_RAW_PROMPT_REFERENCE_EVIDENCE_ANSWER_AND_JUDGE_OUTPUT",
        "repository_retention": "PROHIBITED_RAW_REPO_EXTERNAL_ONLY",
        "records": raw_records,
    }
    return report, raw_sidecar


def _partial_report(
    error: Exception, *, run_id: str, journal_path: Path
) -> dict[str, Any]:
    journal = _journal_summary(journal_path, run_id)
    return {
        "schema": "milai.dg10.tier3-same-vllm-judge.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "run_id": run_id,
        "status": "FAIL_PARTIAL_TIER3_CHARACTERIZATION",
        "quality_outcome": "NOT_EVALUABLE",
        "release_input": False,
        "test_access_authorized": False,
        "test_labels_or_outputs_opened": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "failure": {
            "type": type(error).__name__,
            "reason_sha256": _sha256_bytes(str(error).encode()),
        },
        "repo_external_sidecar": {"status": "NOT_WRITTEN_FOR_PARTIAL_FAILURE"},
        "repo_external_progress_journal": journal,
        "completed_native_model_calls": journal["completed_native_model_calls"],
        "release_effect": {"may_authorize_test": False},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the DG-10 same-vLLM Tier-3 dev characterization"
    )
    parser.add_argument("--execute-local-vllm", action="store_true")
    parser.add_argument("--data-boundary-ack")
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--identity-report", type=Path, default=IDENTITY_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY
    )
    args = parser.parse_args()
    if not args.execute_local_vllm or args.data_boundary_ack != DATA_BOUNDARY_ACK:
        raise Tier3JudgeError(
            "Tier-3 requires the execution flag and exact public-dev characterization ack"
        )
    for path, expected in (
        (QUALITY_CONTRACT, QUALITY_CONTRACT_SHA256),
        (QUALITY_REPORT, QUALITY_REPORT_SHA256),
        (THREE_ARM_REPORT, THREE_ARM_REPORT_SHA256),
        (THREE_ARM_SIDECAR, THREE_ARM_SIDECAR_SHA256),
    ):
        if _sha256_file(path) != expected:
            raise Tier3JudgeError(f"bound input drift: {path.name}")
    sidecar = tier2._load_bound(THREE_ARM_SIDECAR, THREE_ARM_SIDECAR_SHA256)
    capture_directory = dev_smoke._validate_capture_directory(args.capture_directory)
    client = dev_smoke.LocalVllmClient(
        args.base_url, args.identity_report.resolve(), args.timeout
    )
    run_id = f"dg10-tier3-judge-{DATE}-{uuid4().hex[:12]}"
    journal_path = capture_directory / f"{run_id}.progress.jsonl"
    try:
        report, raw_sidecar = run_judge(
            client=client,
            sidecar=sidecar,
            run_id=run_id,
            journal_path=journal_path,
        )
    except Exception as exc:
        partial = _partial_report(exc, run_id=run_id, journal_path=journal_path)
        dev_smoke._write_new(args.output.resolve(), dev_smoke._encoded_json(partial))
        raise
    raw = dev_smoke._encoded_json(raw_sidecar)
    sidecar_path = capture_directory / f"{report['run_id']}.raw.json"
    dev_smoke._write_new(sidecar_path, raw)
    report["repo_external_sidecar"] = {
        "status": "WRITTEN_HASH_BOUND",
        "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        "sha256": _sha256_bytes(raw),
        "size": len(raw),
        "mode": "0600",
    }
    report_raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), report_raw)
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(args.output.resolve()),
                "sha256": _sha256_bytes(report_raw),
                "sidecar": str(sidecar_path),
                "sidecar_sha256": _sha256_bytes(raw),
                "progress_journal": str(journal_path),
                "progress_journal_sha256": report["repo_external_progress_journal"][
                    "sha256"
                ],
                "native_model_calls": report["aggregates"]["native_model_calls"],
                "release_input": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
